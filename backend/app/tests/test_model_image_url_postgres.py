"""PostgreSQL behavior of URL image creation on an approved disposable target.

Uses the existing migrated-database fixture; no test-specific schema changes.
The concurrent empty-parent test characterizes the current lack of a unique
primary-image constraint. It does not make multiple primaries a desired policy.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import event, select

from app.libs.dto.catalog.model_image_input import ModelImageIn
from app.models.catalog import models_service
from app.schemas import AuditLog, ModelImage, User

pytest_plugins = ("app.tests.test_modelcolor_create_postgres",)


def _audits(db, model_id):
    return db.scalars(select(AuditLog).where(
        AuditLog.entity_type == "ModelImage",
        AuditLog.new_value_json["model_id"].as_integer() == model_id,
    ).order_by(AuditLog.id)).all()


def test_postgres_url_create_persists_image_and_real_audit(pg_sessions, pg_case):
    mid = pg_case["models"]["standard"]
    actor_id = pg_case["actors"]["standard"]
    with pg_sessions() as db:
        result = models_service.add_image(db.get(User, actor_id), db, mid, ModelImageIn(
            file_url=" https://example.invalid/garment.png ", image_type=" MODEL ", is_primary=True,
        ))
    with pg_sessions() as db:
        image = db.get(ModelImage, result["id"])
        assert (image.model_id, image.file_url, image.image_type, image.is_primary) == (
            mid, "https://example.invalid/garment.png", "model", True,
        )
        entries = _audits(db, mid)
        assert len(entries) == 1
        entry = entries[0]
        assert (entry.user_id, entry.action, entry.entity_id) == (actor_id, "create", image.id)
        assert entry.new_value_json == {"model_id": mid, "file_url": image.file_url}
        assert entry.entry_hash and len(entry.entry_hash) == 64


def test_postgres_before_commit_failure_rolls_back_primary_insert_and_audit(pg_sessions, pg_case):
    mid = pg_case["models"]["standard"]
    actor_id = pg_case["actors"]["standard"]
    with pg_sessions.begin() as db:
        old = ModelImage(model_id=mid, file_url="https://example.invalid/old", is_primary=True)
        db.add(old)
        db.flush()
        old_id = old.id
    with pg_sessions() as db:
        actor = db.get(User, actor_id)
        def fail_after_audit_queued(_session):
            raise RuntimeError("injected before-commit failure")
        event.listen(db, "before_commit", fail_after_audit_queued)
        with pytest.raises(RuntimeError, match="injected before-commit failure"):
            models_service.add_image(actor, db, mid, ModelImageIn(
                file_url="https://example.invalid/new", is_primary=True,
            ))
        db.rollback()
    with pg_sessions() as db:
        images = db.scalars(select(ModelImage).where(ModelImage.model_id == mid)).all()
        assert [(image.id, image.file_url, image.is_primary) for image in images] == [
            (old_id, "https://example.invalid/old", True),
        ]
        assert _audits(db, mid) == []


def test_postgres_concurrent_primary_creates_on_empty_model_characterize_race(pg_sessions, pg_case):
    mid = pg_case["models"]["standard"]
    actor_id = pg_case["actors"]["standard"]
    barrier = Barrier(2, timeout=15)

    def create(suffix):
        with pg_sessions() as db:
            actor = db.get(User, actor_id)
            connection = db.connection()
            def after_update(_conn, _cursor, statement, _parameters, _context, _many):
                if statement.lstrip().lower().startswith("update model_images"):
                    barrier.wait()
            event.listen(connection, "after_cursor_execute", after_update)
            try:
                return models_service.add_image(actor, db, mid, ModelImageIn(
                    file_url=f"https://example.invalid/{suffix}", is_primary=True,
                ))["id"]
            finally:
                event.remove(connection, "after_cursor_execute", after_update)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(create, suffix) for suffix in ("one", "two")]
        ids = [future.result(timeout=40) for future in futures]
    with pg_sessions() as db:
        images = db.scalars(select(ModelImage).where(ModelImage.model_id == mid)).all()
        assert {image.id for image in images} == set(ids)
        assert all(image.is_primary for image in images)
        entries = _audits(db, mid)
        assert {entry.entity_id for entry in entries} == set(ids)
        assert entries[1].prev_hash == entries[0].entry_hash
