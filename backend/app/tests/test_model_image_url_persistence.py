"""Parity and rollback coverage for the URL image creation write boundary."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.libs.dto.catalog.model_image_input import ModelImageIn
from app.models.catalog import models_service
from app.schemas import Model, ModelImage


@pytest.fixture
def db_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Model.__table__.create(engine)
    ModelImage.__table__.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add_all([Model(code="IMAGE-A", name="A"), Model(code="IMAGE-B", name="B")])
        db.flush()
        ids = [m.id for m in db.scalars(select(Model).order_by(Model.id))]
        db.add_all([ModelImage(model_id=i, file_url="https://old.test/a", is_primary=True) for i in ids])
        db.commit()
    yield factory, ids
    engine.dispose()


def test_url_create_preserves_scope_primary_and_audit(db_factory, monkeypatch):
    factory, ids = db_factory
    events = []
    monkeypatch.setattr(models_service, "log_action", lambda db, actor, action, entity, entity_id, **kw: events.append((action, entity, entity_id, kw["new_value"])))
    with factory() as db:
        result = models_service.add_image(SimpleNamespace(id=1), db, ids[0], ModelImageIn(
            file_url="  https://example.test/new.png  ", image_type=" MATERIAL ", is_primary=True,
        ))
        rows = db.scalars(select(ModelImage).order_by(ModelImage.id)).all()
        assert [row.is_primary for row in rows] == [False, True, True]
        assert rows[-1].file_url == "https://example.test/new.png"
        assert rows[-1].image_type == "material"
        assert events == [("create", "ModelImage", result["id"], {"model_id": ids[0], "file_url": rows[-1].file_url})]
    with factory() as db:
        assert db.get(ModelImage, result["id"]).is_primary


def test_audit_failure_rolls_back_insert_and_primary_change(db_factory, monkeypatch):
    factory, ids = db_factory
    def fail(*args, **kwargs):
        raise RuntimeError("audit failure")
    monkeypatch.setattr(models_service, "log_action", fail)
    with factory() as db:
        with pytest.raises(RuntimeError):
            models_service.add_image(SimpleNamespace(id=1), db, ids[0], ModelImageIn(file_url="https://example.test/new", is_primary=True))
        db.rollback()
    with factory() as db:
        rows = db.scalars(select(ModelImage).order_by(ModelImage.id)).all()
        assert len(rows) == 2
        assert all(row.is_primary for row in rows)


def test_invalid_url_and_type_leave_existing_rows_unchanged(db_factory):
    factory, ids = db_factory
    with factory() as db:
        for payload in (ModelImageIn(file_url="javascript:bad", is_primary=True), ModelImageIn(file_url="https://example.test/a", image_type="print", is_primary=True)):
            with pytest.raises(HTTPException) as error:
                models_service.add_image(SimpleNamespace(id=1), db, ids[0], payload)
            assert error.value.status_code == 400
        rows = db.scalars(select(ModelImage)).all()
        assert len(rows) == 2 and all(row.is_primary for row in rows)
