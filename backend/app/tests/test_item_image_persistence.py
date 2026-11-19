from uuid import uuid4

import pytest

from app.db import session as session_module
from app.core.security import create_access_token
from app.models.inventory import stock_service
from app.schemas import AuditLog, Item, Role, User


def _item():
    with session_module.SessionLocal() as db:
        item = Item(sku=f"IMG-{uuid4().hex}", name="Image item", category="fabric", unit="kg")
        db.add(item)
        db.commit()
        return item.id


def test_item_image_normalization_refusals_and_persistence(client, auth_headers):
    item_id = _item()
    path = f"/api/inventory/items/{item_id}/image"
    assert client.patch(path, json={"image_url": "https://example.com/a.png"}).status_code == 401
    with session_module.SessionLocal() as db:
        role = Role(name=f"image-denied-{uuid4().hex}", permissions=[])
        db.add(role)
        db.flush()
        user = User(name="Denied", email=f"{uuid4().hex}@example.invalid", password_hash="unused", role_id=role.id)
        db.add(user)
        db.commit()
        denied = {"Authorization": f"Bearer {create_access_token(str(user.id))}"}
    assert client.patch(path, headers=denied, json={"image_url": "https://example.com/a.png"}).status_code == 403
    updated = client.patch(path, headers=auth_headers, json={"image_url": "  https://example.com/a.png  "})
    assert updated.status_code == 200
    assert updated.json()["image_url"] == "https://example.com/a.png"
    assert client.patch(path, headers=auth_headers, json={"image_url": "javascript:alert(1)"}).status_code == 400
    assert client.patch("/api/inventory/items/999999999/image", headers=auth_headers, json={"image_url": "file:x"}).status_code == 404
    with session_module.SessionLocal() as db:
        assert db.get(Item, item_id).image_url == "https://example.com/a.png"
        assert db.query(AuditLog).filter_by(entity_type="Item", entity_id=item_id, action="update_image").count() == 1
    cleared = client.patch(path, headers=auth_headers, json={"image_url": "   "})
    assert cleared.status_code == 200
    assert cleared.json()["image_url"] is None
    with session_module.SessionLocal() as db:
        assert db.get(Item, item_id).image_url is None


def test_item_image_audit_failure_rolls_back(client, auth_headers, monkeypatch):
    item_id = _item()
    original = stock_service.log_action

    def fail_after_audit(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(stock_service, "log_action", fail_after_audit)
    with pytest.raises(RuntimeError, match="injected audit failure"):
        client.patch(f"/api/inventory/items/{item_id}/image", headers=auth_headers,
                     json={"image_url": "/storage/model-files/example.png"})
    with session_module.SessionLocal() as db:
        assert db.get(Item, item_id).image_url is None
        assert db.query(AuditLog).filter_by(entity_type="Item", entity_id=item_id, action="update_image").count() == 0
