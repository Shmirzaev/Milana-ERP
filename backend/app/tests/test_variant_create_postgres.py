"""Variant creation on an approved disposable, migrated PostgreSQL database."""
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event
from time import monotonic, sleep

import sqlalchemy as sa

import pytest

from app.libs.dto.catalog.model_input import ModelVariantCreateIn
from app.models import numbering_service as numbering
from app.models.catalog import models_service
from app.schemas import (AuditLog, Brand, Collection, CollectionModel, Item, Model, ModelBOM,
                         ModelColor, ModelImage, ModelSize, Role, SystemSetting, User)
from app.tests.test_fg_model_numbering_postgres import fg_pg_sessions  # noqa: F401


def seed(sessions):
    with sessions.begin() as db:
        actor = User(email="variant-pg@example.invalid", name="Synthetic", password_hash="unused", role=Role(name="variant-pg", permissions=["*"]))
        source = Model(code="PGVAR100", name="Synthetic", catalog_scope="standard",
                       details_json={"general": {"model_no": "PGVAR100"}})
        fabric = Item(sku="SYNTH-FABRIC", name="Synthetic fabric", category="fabric", unit="kg")
        brand = Brand(name="Synthetic brand")
        db.add_all([actor, source, fabric, brand]); db.flush()
        collection = Collection(brand_id=brand.id, name="Synthetic", year=2026)
        db.add(collection); db.flush()
        db.add_all([ModelSize(model_id=source.id, size="M", measurement_json={"length": 1}),
                    ModelColor(model_id=source.id, color_name="blue"),
                    ModelImage(model_id=source.id, file_url="/pattern.gem", image_type="pattern", is_primary=True),
                    ModelBOM(model_id=source.id, item_id=fabric.id, quantity_per_piece=1, unit="kg", waste_percent=0),
                    CollectionModel(collection_id=collection.id, model_id=source.id)])
        return actor.id, source.id


def test_pg_variant_late_failure_rolls_back_counter_children_and_audit(fg_pg_sessions, monkeypatch):
    sessions, _ = fg_pg_sessions
    actor_id, source_id = seed(sessions)
    with sessions() as db:
        original_log = models_service.log_action
        def fail(*args, **kwargs):
            original_log(*args, **kwargs)
            db.flush()
            raise RuntimeError("late audit failure")
        with monkeypatch.context() as patch:
            patch.setattr(models_service, "log_action", fail)
            with pytest.raises(RuntimeError, match="late audit failure"):
                models_service.create_model_variant(db.get(User, actor_id), db, source_id, ModelVariantCreateIn(color="red", picture_url="/storage/model-files/fabric.png", print_picture_url="/storage/model-files/print.png"), "standard")
        db.rollback()
    with sessions() as db:
        assert db.query(Model).count() == 1
        assert db.query(ModelSize).count() == db.query(ModelColor).count() == db.query(ModelImage).count() == 1
        assert db.query(ModelBOM).count() == db.query(CollectionModel).count() == 1
        assert db.query(AuditLog).count() == 0
        assert db.query(SystemSetting).filter_by(key=numbering.MODEL_VARIANT_SETTING_KEY).one_or_none() is None
        result = models_service.create_model_variant(db.get(User, actor_id), db, source_id, ModelVariantCreateIn(color="red", picture_url="/storage/model-files/fabric.png", print_picture_url="/storage/model-files/print.png"), "standard")
        variant_id = result["id"]
    with sessions() as db:
        variant = db.get(Model, variant_id)
        assert variant.code == "PGVAR100-V-6455"
        assert [row.size for row in variant.sizes] == ["M"]
        assert [row.color_name for row in variant.colors] == ["blue"]
        assert {(row.image_type, row.is_primary) for row in variant.images} == {("pattern", False), ("material", False), ("print", False)}
        assert [(row.color, row.photo_url) for row in variant.bom] == [("red", "/storage/model-files/fabric.png")]
        assert db.query(CollectionModel).filter_by(model_id=variant_id).count() == 1
        assert db.query(AuditLog).filter_by(entity_id=variant_id, entity_type="Model", action="create_variant").count() == 1
        assert numbering.next_model_variant_no(db) == "V-6456"


def test_pg_two_automatic_variant_creates_are_distinct(fg_pg_sessions):
    sessions, engine = fg_pg_sessions
    actor_id, source_id = seed(sessions)
    ready, start = Queue(), Event()
    def create():
        with sessions() as db:
            actor = db.get(User, actor_id)
            ready.put(db.scalar(sa.text("SELECT pg_backend_pid()")))
            assert start.wait(10)
            return models_service.create_model_variant(actor, db, source_id, ModelVariantCreateIn(color="red", picture_url="/storage/model-files/fabric.png", print_picture_url="/storage/model-files/print.png"), "standard")["id"]
    with sessions() as holder, ThreadPoolExecutor(max_workers=2) as pool:
        holder.execute(sa.text("SELECT pg_advisory_xact_lock(:namespace, hashtext(:resource))"),
                       {"namespace": numbering._NUMBERING_LOCK_NAMESPACE,
                        "resource": numbering.MODEL_VARIANT_SETTING_KEY})
        futures = [pool.submit(create) for _ in range(2)]
        try:
            pids = [ready.get(timeout=10) for _ in futures]
            start.set()
            deadline = monotonic() + 10
            waiting = False
            while monotonic() < deadline:
                with engine.connect() as connection:
                    waiting = all(connection.scalar(sa.text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                                                    {"pid": pid}) for pid in pids)
                if waiting:
                    break
                sleep(0.02)
            assert waiting, "Both variant creates must wait on the held numbering lock"
        finally:
            holder.rollback()
            start.set()
        ids = [future.result(timeout=30) for future in futures]
    with sessions() as db:
        codes = sorted(row.code for row in db.query(Model).filter(Model.id.in_(ids)).all())
        assert codes == ["PGVAR100-V-6455", "PGVAR100-V-6456"]
        assert db.query(AuditLog).filter(AuditLog.entity_id.in_(ids), AuditLog.entity_type == "Model", AuditLog.action == "create_variant").count() == 2
        assert numbering.next_model_variant_no(db) == "V-6457"
