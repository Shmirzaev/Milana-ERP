"""Variant creation shares its caller's transaction and copies only selected children."""
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db.base import Base
from app.libs.dto.catalog.model_input import ModelVariantCreateIn
from app.models.catalog import models_service
from app.schemas import AuditLog, Model, ModelColor, ModelImage, ModelSize, Role, User


def test_variant_creation_rolls_back_all_rows_on_late_audit_failure(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as db:
        actor = User(email="variant@example.invalid", name="Synthetic", password_hash="unused", role=Role(name="admin", permissions=["*"]))
        source = Model(code="USL100", name="Synthetic", catalog_scope="usluga", factory_code="ECO",
                       details_json={"general": {"model_no": "USL100"}})
        db.add_all([actor, source]); db.flush()
        db.add_all([ModelSize(model_id=source.id, size="M", measurement_json={"length": 1}),
                    ModelColor(model_id=source.id, color_name="blue"),
                    ModelImage(model_id=source.id, file_url="/pattern.gem", image_type="pattern", is_primary=True),
                    ModelImage(model_id=source.id, file_url="/old.png", image_type="print", is_primary=False)])
        db.commit()
        calls = []
        event.listen(db, "after_commit", lambda *args: calls.append("commit"))
        def fail(*args, **kwargs):
            db.flush()
            raise RuntimeError("late audit failure")
        with monkeypatch.context() as patch:
            patch.setattr(models_service, "log_action", fail)
            with pytest.raises(RuntimeError, match="late audit failure"):
                models_service.create_model_variant(actor, db, source.id, ModelVariantCreateIn(variant_no="V-1"), "usluga")
        assert calls == []
        db.rollback()
        assert db.query(Model).count() == 1
        assert db.query(ModelSize).count() == 1
        assert db.query(ModelColor).count() == 1
        assert db.query(ModelImage).count() == 2
        assert db.query(AuditLog).count() == 0
        result = models_service.create_model_variant(actor, db, source.id, ModelVariantCreateIn(variant_no="V-1"), "usluga")
        variant = db.get(Model, result["id"])
        assert variant.code == "USL100-V-1" and variant.factory_code == "ECO"
        assert [row.size for row in variant.sizes] == ["M"]
        assert [row.color_name for row in variant.colors] == ["blue"]
        assert [(row.image_type, row.is_primary) for row in variant.images] == [("pattern", False)]
        assert db.query(AuditLog).filter_by(action="create_variant", entity_id=variant.id).count() == 1
        assert calls == ["commit"]
    engine.dispose()
