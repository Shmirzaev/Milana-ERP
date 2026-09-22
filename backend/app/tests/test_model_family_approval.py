import pytest
from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import AuditLog, Item, Model, ModelBOM


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


def test_approval_audit_failure_rolls_back_the_whole_family(client, auth_headers, monkeypatch):
    from fastapi import HTTPException

    from app.api.routes import catalog

    model_ids = family()
    original_log_action = catalog.log_action
    calls = 0

    def fail_second_audit(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise HTTPException(503, "Synthetic approval audit failure")
        return original_log_action(*args, **kwargs)

    monkeypatch.setattr(catalog, "log_action", fail_second_audit)
    response = client.post(f"/api/models/{model_ids[0]}/approve", headers=auth_headers)
    assert response.status_code == 503, response.text

    with SessionLocal() as db:
        rows = db.query(Model).filter(Model.id.in_(model_ids)).order_by(Model.id).all()
        assert [row.status for row in rows] == ["draft", "draft", "draft"]
        assert all(row.approved_by is None and row.approved_at is None for row in rows)
        assert db.query(AuditLog).filter(
            AuditLog.action == "approve",
            AuditLog.entity_type == "Model",
            AuditLog.entity_id.in_(model_ids),
        ).count() == 0


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


def test_usluga_approval_batches_main_fabric_counts():
    from sqlalchemy import event
    from app.db.session import engine
    from app.api.routes.catalog import approve_model
    from app.models import User

    with SessionLocal() as db:
        actor = db.query(User).filter(User.email == "admin@example.com").one()
        rows = [Model(code="USAPP901" + suffix, name="Batch approval family", status="draft",
                      catalog_scope="usluga", factory_code="ECO",
                      details_json={"general": {"model_no": "USAPP901", "variant_no": suffix}})
                for suffix in ("", "V1", "V2")]
        db.add_all(rows)
        db.flush()
        db.add_all([
            ModelBOM(model_id=row.id, material_name="Main fabric", material_role="main",
                     quantity_per_piece=1, unit="kg", waste_percent=0)
            for row in rows
        ])
        db.commit()
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if "count(model_bom.id)" in normalized and "group by model_bom.model_id" in normalized:
                statements.append(statement)

        event.listen(engine, "before_cursor_execute", capture)
        try:
            approve_model(rows[0].id, db, actor, "usluga")
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert len(statements) == 1


@pytest.mark.parametrize("unrelated_count", [1, 50, 401])
def test_approval_family_does_not_hydrate_unrelated_catalog_rows(unrelated_count):
    from uuid import uuid4

    from app.api.routes.catalog import _approval_family

    marker = uuid4().hex[:8]
    model_no = f"APPROVAL%_{marker}"
    with SessionLocal() as db:
        source = Model(
            code=f"APPROVAL-SOURCE-{marker}",
            name="Approval source",
            catalog_scope="standard",
            details_json={"general": {"model_no": model_no}},
        )
        sibling = Model(
            code=f"APPROVAL-SIBLING-{marker}",
            name="Approval sibling",
            catalog_scope="standard",
            details_json={"general": {"model_no": model_no, "variant_no": "V-2"}},
        )
        legacy = Model(
            code=f"APPROVAL-LEGACY-{marker}",
            name="Approval legacy import",
            catalog_scope="standard",
            details_json={"legacy_import": True, "general": {"model_no": model_no}},
        )
        other_scope = Model(
            code=f"APPROVAL-USLUGA-{marker}",
            name="Approval other scope",
            catalog_scope="usluga",
            factory_code="ECO",
            details_json={"general": {"model_no": model_no}},
        )
        unrelated = [
            Model(
                code=f"APPROVAL-OTHER-{marker}-{index}",
                name="Unrelated approval model",
                catalog_scope="standard",
                details_json={"general": {"model_no": f"OTHER-{marker}-{index}"}},
            )
            for index in range(unrelated_count)
        ]
        db.add_all([source, sibling, legacy, other_scope, *unrelated])
        db.commit()
        source_id = int(source.id)
        sibling_id = int(sibling.id)
        tracked_ids = {sibling_id, *(int(row.id) for row in unrelated)}
        db.expunge_all()
        source = db.get(Model, source_id)
        loaded_ids: list[int] = []

        def capture_load(target, _context):
            if int(target.id) in tracked_ids:
                loaded_ids.append(int(target.id))

        event.listen(Model, "load", capture_load)
        try:
            family_rows = _approval_family(db, source)
        finally:
            event.remove(Model, "load", capture_load)

    assert [int(row.id) for row in family_rows] == [source_id, sibling_id]
    assert loaded_ids == [sibling_id]
