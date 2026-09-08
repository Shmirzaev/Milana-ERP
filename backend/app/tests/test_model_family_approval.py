from app.db.session import SessionLocal
from app.models import Item, Model, ModelBOM


def family():
    with SessionLocal() as db:
        fabric = db.query(Item).filter(Item.category == "fabric").first()
        ids = []
        for variant in ("", "V-1", "V-2"):
            row = Model(code="APPROVAL900" + ("-" + variant if variant else ""),
                        name="Approval family", status="draft", catalog_scope="standard",
                        details_json={"general": {"model_no": "APPROVAL900", "variant_no": variant}})
            db.add(row)
            db.flush()
            db.add(ModelBOM(model_id=row.id, item_id=fabric.id, quantity_per_piece=1, unit="kg", waste_percent=0))
            ids.append(row.id)
        db.commit()
        return ids


def variant(client, headers, mid, number):
    response = client.post(f"/api/models/{mid}/variants", json={"variant_no": number}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_one_approval_covers_existing_and_future_variants(client, auth_headers):
    base, first, second = family()
    pending = variant(client, auth_headers, first, "V-3")
    assert pending["status"] == "draft"
    def production(mid):
        return client.post("/api/planning/create-branded-production", headers=auth_headers,
                           json={"production_type": "branded_stock", "model_id": mid, "planned_quantity": 10, "items": []})
    assert production(pending["id"]).status_code == 400
    approved = client.post(f"/api/models/{second}/approve", headers=auth_headers)
    assert approved.status_code == 200, approved.text
    for mid in (base, first, second, pending["id"]):
        row = client.get(f"/api/models/{mid}", headers=auth_headers).json()
        assert row["status"] == "approved"
        assert row["approved_at"] == approved.json()["approved_at"]
    again = client.post(f"/api/models/{base}/approve", headers=auth_headers)
    assert again.json()["approved_at"] == approved.json()["approved_at"]
    future = variant(client, auth_headers, base, "V-4")
    assert future["status"] == "approved"
    assert future["approved_at"] == approved.json()["approved_at"]
    created = production(future["id"])
    assert created.status_code == 201, created.text
    with SessionLocal() as db:
        from app.models import WorkOrder
        assert db.query(WorkOrder).filter(WorkOrder.production_order_id == created.json()["id"]).count() > 0


def test_legacy_sibling_approval_is_inherited_without_approving_base(client, auth_headers):
    base, first, second = family()
    with SessionLocal() as db:
        db.get(Model, first).status = "approved"
        db.commit()
    created = variant(client, auth_headers, base, "V-3")
    assert created["status"] == "approved"
    assert client.get(f"/api/models/{base}", headers=auth_headers).json()["status"] == "draft"
    groups = client.get("/api/models/variant-groups?q=APPROVAL900&compact=true", headers=auth_headers)
    assert groups.status_code == 200, groups.text
    assert groups.json()[0]["status"] == "approved"
    direct = client.post("/api/models", headers=auth_headers, json={"code": "APPROVAL900-V-4", "name": "Direct variant",
                         "details_json": {"general": {"model_no": "APPROVAL900", "variant_no": "V-4"}}})
    assert direct.status_code == 201, direct.text
    assert direct.json()["status"] == "approved"
    new = client.post("/api/models", headers=auth_headers, json={"code": "APPROVAL901", "name": "New model"})
    assert new.json()["status"] == "draft"
    clone = client.post(f"/api/models/{created['id']}/clone", headers=auth_headers)
    assert clone.status_code == 201, clone.text
    assert clone.json()["status"] == "draft"


def test_approval_permission_and_family_scope(client, auth_headers):
    base, first, second = family()
    with SessionLocal() as db:
        from app.models import User
        modeler = db.query(User).filter(User.email == "modeling@example.com").one()
        modeler.role.permissions = ["modeling.models"]
        modeler.extra_permissions = []
        unrelated = Model(code="UNRELATED900", name="Unrelated", status="draft", catalog_scope="standard")
        eco = Model(code="ECO-APPROVAL900", name="Other scope", status="draft", catalog_scope="usluga", factory_code="ECO",
                    details_json={"general": {"model_no": "APPROVAL900"}})
        db.add_all([unrelated, eco])
        db.commit()
        other_ids = [unrelated.id, eco.id]
    login = client.post("/api/auth/token", data={"username": "modeling@example.com", "password": "demo12345"})
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    denied = client.post(f"/api/models/{first}/approve", headers=headers)
    assert denied.status_code == 403, denied.text
    with SessionLocal() as db:
        assert all(db.get(Model, mid).status == "draft" for mid in (base, first, second))
    assert client.post(f"/api/models/{base}/approve", headers=auth_headers).status_code == 200
    with SessionLocal() as db:
        assert all(db.get(Model, mid).status == "draft" for mid in other_ids)
    assert variant(client, headers, base, "V-3")["status"] == "approved"


def test_usluga_family_validates_all_main_fabrics_before_approval(client, auth_headers):
    import pytest
    from fastapi import HTTPException
    from app.api.routes.catalog import approve_model
    from app.models import User
    with SessionLocal() as db:
        actor = db.query(User).filter(User.email == "admin@example.com").one()
        rows = [Model(code="USAPP900" + suffix, name="Service family", status="draft",
                      catalog_scope="usluga", factory_code="ECO",
                      details_json={"general": {"model_no": "USAPP900", "variant_no": suffix}})
                for suffix in ("", "V1")]
        db.add_all(rows)
        db.flush()
        db.add(ModelBOM(model_id=rows[0].id, material_name="Main fabric", material_role="main",
                        quantity_per_piece=1, unit="kg", waste_percent=0))
        db.commit()
        with pytest.raises(HTTPException) as error:
            approve_model(rows[0].id, db, actor, "usluga")
        assert error.value.status_code == 409
        assert all(row.status == "draft" for row in rows)
        db.add(ModelBOM(model_id=rows[1].id, material_name="Main fabric", material_role="main",
                        quantity_per_piece=1, unit="kg", waste_percent=0))
        db.commit()
        approve_model(rows[0].id, db, actor, "usluga")
        assert all(row.status == "approved" for row in rows)
