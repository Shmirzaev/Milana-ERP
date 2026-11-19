from uuid import uuid4

import pytest

from app.models.catalog import models_service
from app.schemas import AuditLog, Item, Model, ModelBOM, ModelImage
from app.tests.conftest import TestSessionLocal


def test_variant_patch_rolls_back_all_writes_if_audit_fails(client, auth_headers, monkeypatch):
    model_no = f"PATCH-{uuid4().hex[:8]}"
    with TestSessionLocal() as db:
        fabric = db.query(Item).filter(Item.category == "fabric").first()
        assert fabric is not None
        source = Model(code=f"{model_no}-A", name="Source", status="draft",
                       details_json={"general": {"model_no": model_no, "variant_no": "A"}})
        target = Model(code=f"{model_no}-B", name="Target", status="draft",
                       details_json={"general": {"model_no": model_no, "variant_no": "B"},
                                     "extension": {"preserve": "yes"}})
        db.add_all([source, target])
        db.flush()
        db.add_all([
            ModelBOM(model_id=source.id, item_id=fabric.id, color="blue", unit="kg", quantity_per_piece=1),
            ModelBOM(model_id=target.id, item_id=fabric.id, color="blue", unit="kg", quantity_per_piece=1),
            ModelImage(model_id=target.id, image_type="material", file_url="/storage/model-files/old.png", is_primary=False),
            ModelImage(model_id=target.id, image_type="print", file_url="/storage/model-files/old-print.png", is_primary=False),
        ])
        db.commit()
        source_id, target_id = source.id, target.id

    original_log_action = models_service.log_action

    def fail_after_audit(*args, **kwargs):
        original_log_action(*args, **kwargs)
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(models_service, "log_action", fail_after_audit)
    payload = {"variant_no": "C", "color": "red", "picture_url": "/storage/model-files/new.png",
               "print_picture_url": None}
    with pytest.raises(RuntimeError, match="injected audit failure"):
        client.patch(f"/api/models/{source_id}/variants/{target_id}", json=payload, headers=auth_headers)

    with TestSessionLocal() as db:
        target = db.get(Model, target_id)
        assert target.code == f"{model_no}-B"
        assert target.details_json["general"]["variant_no"] == "B"
        assert target.details_json["extension"] == {"preserve": "yes"}
        assert target.bom[0].color == "blue"
        assert {image.image_type: image.file_url for image in target.images} == {
            "material": "/storage/model-files/old.png", "print": "/storage/model-files/old-print.png"
        }
        assert db.query(AuditLog).filter_by(action="update_variant", entity_id=target_id).count() == 0

    monkeypatch.setattr(models_service, "log_action", original_log_action)
    response = client.patch(f"/api/models/{source_id}/variants/{target_id}", json=payload, headers=auth_headers)
    assert response.status_code == 200, response.text
    with TestSessionLocal() as db:
        target = db.get(Model, target_id)
        assert target.code == f"{model_no}-C"
        assert target.details_json["extension"] == {"preserve": "yes"}
        assert target.bom[0].color == "red"
        assert {image.image_type: image.file_url for image in target.images} == {
            "material": "/storage/model-files/new.png"
        }
        assert db.query(AuditLog).filter_by(action="update_variant", entity_id=target_id).count() == 1
