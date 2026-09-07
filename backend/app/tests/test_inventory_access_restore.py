from datetime import datetime, timezone

import pytest

from app.core.security import create_access_token
from app.db import session as session_module
from app.models import AuditLog, Department, Item, Role, StockBatch, StockMovement, User, Warehouse


@pytest.fixture
def scoped_headers():
    with session_module.SessionLocal() as db:
        user = User(name="Material keeper", email="material-keeper@example.com", password_hash="unused",
                    role_id=db.query(Role).filter_by(name="Storage").one().id,
                    department_id=db.query(Department).filter_by(code="STR").one().id,
                    extra_permissions=["inventory.materials_only", "inventory.batches.delete", "inventory.force_override"])
        db.add(user)
        db.commit()
        return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


def make_batch(category="fabric", quantity=0, explicit_archive=True):
    with session_module.SessionLocal() as db:
        item = db.query(Item).filter_by(category=category).first()
        warehouse = db.query(Warehouse).filter_by(type="fabric_storage" if category == "fabric" else "accessory_storage").first()
        batch = StockBatch(item_id=item.id, batch_no="RESTORE-TEST", quantity=quantity, unit=item.unit,
                           warehouse_id=warehouse.id, qc_status="hold", roll_weights_kg=[10], piece_count=1,
                           archived_at=datetime.now(timezone.utc) if explicit_archive else None)
        db.add(batch)
        db.flush()
        db.add(StockMovement(item_id=item.id, batch_id=batch.id, movement_type="receive", quantity=10,
                             unit=item.unit, to_warehouse_id=warehouse.id, reference_type="StockBatch", reference_id=batch.id))
        db.add(StockMovement(item_id=item.id, batch_id=batch.id, movement_type="consume", quantity=10,
                             unit=item.unit, from_warehouse_id=warehouse.id, reference_type="ProductionOrder", reference_id=1))
        db.commit()
        return batch.id, item.id


@pytest.mark.parametrize("suffix", ["items?group=accessories", "stock?group=accessories", "batches?group=accessories",
                                     "items?category=packaging", "accessory-issues", "accessory-issue-requests",
                                     "accessory-issue-plan?production_order_id=1"])
def test_material_only_blocks_accessory_reads(client, scoped_headers, suffix):
    response = client.get(f"/api/inventory/{suffix}", headers=scoped_headers)
    assert response.status_code == 403, response.text


def test_material_scope_filters_omitted_group_and_preserves_other_users(client, scoped_headers, auth_headers):
    make_batch("accessory", 10, False)
    with session_module.SessionLocal() as db:
        allowed_ids = {item.id for item in db.query(Item).filter(Item.category.in_(("fabric", "semi_finished"))).all()}
    for endpoint in ("items", "stock", "batches"):
        response = client.get(f"/api/inventory/{endpoint}", headers=scoped_headers)
        assert response.status_code == 200, response.text
        assert all(row["id" if endpoint == "items" else "item_id"] in allowed_ids for row in response.json())
    assert client.get("/api/inventory/stock?group=materials", headers=scoped_headers).status_code == 200
    assert client.get("/api/inventory/stock?group=accessories", headers=auth_headers).status_code == 200
    with session_module.SessionLocal() as db:
        from app.services.price_calculation import is_accessory_pricing_user
        scoped = db.query(User).filter_by(email="material-keeper@example.com").one()
        assert not is_accessory_pricing_user(scoped)
        scoped.extra_permissions = []
        assert is_accessory_pricing_user(scoped)


def test_material_only_blocks_accessory_id_bypasses(client, scoped_headers):
    batch_id, item_id = make_batch("accessory", 10, False)
    cases = [
        ("patch", f"/batches/{batch_id}", {"quantity": 2}),
        ("delete", f"/batches/{batch_id}", None),
        ("patch", f"/stock/{item_id}", {"quantity": 2}),
        ("patch", f"/items/{item_id}/image", {"image_url": None}),
        ("delete", f"/items/{item_id}", None),
        ("post", "/receive", {"item_id": item_id, "batch_no": "BLOCKED", "quantity": 2, "unit": "pcs", "warehouse_id": 1}),
        ("post", "/transfer", {"movement_type": "issue", "item_id": item_id, "batch_id": batch_id, "quantity": 1, "unit": "pcs"}),
    ]
    for method, path, body in cases:
        response = client.request(method, "/api/inventory" + path, headers=scoped_headers, **({"json": body} if body else {}))
        assert response.status_code == 403, (path, response.text)
    with session_module.SessionLocal() as db:
        assert float(db.get(StockBatch, batch_id).quantity) == 10
        assert db.query(StockMovement).filter_by(batch_id=batch_id).count() == 2


@pytest.mark.parametrize("explicit_archive", [True, False])
def test_restore_returns_confirmed_stock_once_and_preserves_history(client, scoped_headers, explicit_archive):
    batch_id, item_id = make_batch(explicit_archive=explicit_archive)
    with session_module.SessionLocal() as db:
        original_ids = [row.id for row in db.query(StockMovement).filter_by(batch_id=batch_id).all()]
    response = client.post(f"/api/inventory/batches/{batch_id}/restore", headers=scoped_headers,
                           json={"quantity": "3.2500", "reason": "Physical stock returned from cutting"})
    assert response.status_code == 200, response.text
    assert response.json()["quantity"] == 3.25
    assert response.json()["qc_status"] == "pending"
    again = client.post(f"/api/inventory/batches/{batch_id}/restore", headers=scoped_headers,
                        json={"quantity": 3.25, "reason": "Duplicate submission"})
    assert again.status_code == 409
    with session_module.SessionLocal() as db:
        batch = db.get(StockBatch, batch_id)
        assert batch.archived_at is None and batch.archived_by is None
        assert batch.roll_weights_kg == [] and batch.piece_count is None
        assert db.query(StockMovement).filter(StockMovement.id.in_(original_ids)).count() == 2
        restored = db.query(StockMovement).filter_by(batch_id=batch_id, reference_type="StockBatchRestore").one()
        assert float(restored.quantity) == 3.25 and restored.movement_type == "return"
        audit = db.query(AuditLog).filter_by(entity_type="StockBatch", entity_id=batch_id, action="restore").one()
        assert audit.new_value_json["reason"] == "Physical stock returned from cutting"
    active = client.get(f"/api/inventory/batches?item_id={item_id}", headers=scoped_headers).json()
    archive = client.get(f"/api/inventory/batches?item_id={item_id}&archived=true", headers=scoped_headers).json()
    assert any(row["id"] == batch_id for row in active)
    assert not any(row["id"] == batch_id for row in archive)


@pytest.mark.parametrize("quantity,reason", [(0, "Counted"), (-1, "Counted"), ("NaN", "Counted"), (1.00001, "Counted"), (1, "   ")])
def test_restore_rejects_invalid_quantity_or_reason(client, scoped_headers, quantity, reason):
    batch_id, _ = make_batch()
    response = client.post(f"/api/inventory/batches/{batch_id}/restore", headers=scoped_headers,
                           json={"quantity": quantity, "reason": reason})
    assert response.status_code == 422, response.text
    with session_module.SessionLocal() as db:
        assert float(db.get(StockBatch, batch_id).quantity) == 0


def test_restore_requires_receive_permission_and_active_material(client, scoped_headers):
    batch_id, item_id = make_batch()
    with session_module.SessionLocal() as db:
        db.get(Item, item_id).is_active = False
        db.commit()
    payload = {"quantity": 2, "reason": "Physical return"}
    response = client.post(f"/api/inventory/batches/{batch_id}/restore", headers=scoped_headers, json=payload)
    assert response.status_code == 409, response.text
    with session_module.SessionLocal() as db:
        user = db.query(User).filter_by(email="material-keeper@example.com").one()
        user.role_id = None
        user.extra_permissions = ["storage.items"]
        db.commit()
    assert client.post(f"/api/inventory/batches/{batch_id}/restore", headers=scoped_headers, json=payload).status_code == 403


def test_material_scope_blocks_accessory_purchase_receipt(client, scoped_headers, auth_headers):
    _, accessory_id = make_batch("accessory", 10, False)
    response = client.post("/api/purchasing/orders", headers=auth_headers, json={
        "lines": [{"item_id": accessory_id, "ordered_quantity": 5, "unit": "pcs", "unit_cost": 1}],
    })
    assert response.status_code == 201, response.text
    order = response.json()
    visible = client.get("/api/purchasing/orders", headers=scoped_headers)
    assert visible.status_code == 200, visible.text
    assert all(row["id"] != order["id"] for row in visible.json())
    blocked = client.post(f"/api/purchasing/orders/{order['id']}/receive", headers=scoped_headers, json={
        "lines": [{"purchase_order_line_id": order["lines"][0]["id"], "received_quantity": 1, "batch_no": "BLOCKED"}],
    })
    assert blocked.status_code == 403, blocked.text


def test_material_scope_checks_batch_when_item_id_is_spoofed(client, scoped_headers):
    accessory_batch_id, _ = make_batch("accessory", 10, False)
    _, fabric_id = make_batch()
    blocked = client.post("/api/inventory/transfer", headers=scoped_headers, json={
        "item_id": fabric_id, "batch_id": accessory_batch_id, "quantity": 1, "unit": "kg", "movement_type": "issue",
    })
    assert blocked.status_code == 403, blocked.text


def test_mubina_restriction_is_targeted_and_idempotent():
    from scripts.restrict_mubina_access import restrict
    with session_module.SessionLocal() as db:
        user = db.get(User, 8)
        user.email = "mubina@milanapremium.uz"
        user.role_id = db.query(Role).filter_by(name="Storage").one().id
        user.extra_permissions = ["inventory.batches.delete", "inventory.force_override"]
        db.commit()
        roles_before = {role.id: list(role.permissions) for role in db.query(Role).all()}
        others_before = {u.id: list(u.extra_permissions) for u in db.query(User).filter(User.id != 8).all()}
        assert restrict(db)["applied"] is False
        assert "inventory.materials_only" not in db.get(User, 8).extra_permissions
        assert restrict(db, apply=True)["applied"] is True
        assert restrict(db, apply=True)["changed"] is False
        assert db.get(User, 8).extra_permissions == ["inventory.batches.delete", "inventory.force_override", "inventory.materials_only"]
        assert roles_before == {role.id: list(role.permissions) for role in db.query(Role).all()}
        assert others_before == {u.id: list(u.extra_permissions) for u in db.query(User).filter(User.id != 8).all()}
        assert db.query(AuditLog).filter_by(action="restrict_accessories").count() == 1
        user.email = "someone-else@example.com"
        db.commit()
        with pytest.raises(RuntimeError, match="identity"):
            restrict(db, apply=True)
