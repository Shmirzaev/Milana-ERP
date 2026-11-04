"""Regression coverage for the catalog model delete transaction and route."""

import pytest

from app.models.catalog import models_service
from app.schemas import AuditLog, CollectionModel, Model, ModelColor, ModelImage, ModelSize, SalesOrderItem, User
from app.tests.conftest import TestSessionLocal


def make_model(scope="standard"):
    db = TestSessionLocal()
    model = Model(code=f"delete-{scope}", name="Delete test", catalog_scope=scope,
                  factory_code="ECO" if scope == "usluga" else None)
    db.add(model)
    db.flush()
    mid = model.id
    db.add_all([CollectionModel(collection_id=1, model_id=mid),
                ModelImage(model_id=mid, file_url="/test"),
                ModelSize(model_id=mid, size="M"),
                ModelColor(model_id=mid, color_name="Blue")])
    db.commit()
    db.close()
    return mid


def test_route_deletes_links_cascades_and_audits(client, auth_headers):
    mid = make_model()
    assert client.delete(f"/api/models/{mid}").status_code == 401
    response = client.delete(f"/api/models/{mid}", headers=auth_headers)
    assert response.status_code == 204, response.text
    db = TestSessionLocal()
    try:
        assert db.get(Model, mid) is None
        for cls in (CollectionModel, ModelImage, ModelSize, ModelColor):
            assert db.query(cls).filter(cls.model_id == mid).count() == 0
        audit = db.query(AuditLog).filter_by(entity_type="Model", entity_id=mid, action="delete").one()
        assert audit.new_value_json == {"code": "delete-standard", "name": "Delete test"}
    finally:
        db.close()


def test_scope_and_sales_reference_refuse_delete(client, auth_headers):
    mid = make_model("usluga")
    assert client.delete(f"/api/models/{mid}", headers=auth_headers).status_code == 404
    assert client.delete(f"/api/usluga/models/{mid}", headers=auth_headers).status_code == 403
    mid = make_model()
    db = TestSessionLocal()
    db.add(SalesOrderItem(sales_order_id=1, model_id=mid, color="Blue", size="M", quantity=1, unit_price=0))
    db.commit()
    db.close()
    response = client.delete(f"/api/models/{mid}", headers=auth_headers)
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "Model is in use by: sales orders"
    db = TestSessionLocal()
    try:
        assert db.get(Model, mid) is not None
        assert db.query(CollectionModel).filter_by(model_id=mid).count() == 1
        assert db.query(AuditLog).filter_by(entity_type="Model", entity_id=mid, action="delete").count() == 0
    finally:
        db.close()


def test_audit_failure_rolls_back_link_and_model_deletion(monkeypatch):
    mid = make_model()
    db = TestSessionLocal()
    current = db.query(User).first()
    def fail_audit(*args, **kwargs):
        raise RuntimeError("audit failure")
    monkeypatch.setattr(models_service, "log_action", fail_audit)
    try:
        with pytest.raises(RuntimeError, match="audit failure"):
            models_service.delete_model(current, db, mid)
        db.rollback()
        assert db.get(Model, mid) is not None
        assert db.query(CollectionModel).filter_by(model_id=mid).count() == 1
        assert db.query(ModelImage).filter_by(model_id=mid).count() == 1
    finally:
        db.close()
