import pytest

from app.schemas import BrandedPlanningOrder, Model, ModelImage, ProductionOrder, WorkOrder
from app.tests.conftest import TestSessionLocal


def payload(model_id=1):
    return {"production_type": "branded_stock", "model_id": model_id, "planned_quantity": 10,
            "items": [{"model_id": model_id, "color": "white", "size": "M", "planned_quantity": 10}]}


@pytest.mark.parametrize("number,file,missing", [
    (False, False, "Enter the Qolip number and attach the Qolip file"),
    (False, True, "Enter the Qolip number on this model"),
    (True, False, "Attach the Qolip file to this model"),
])
def test_bso_rejects_missing_catalog_requirements_without_persisting(client, auth_headers, number, file, missing):
    with TestSessionLocal.begin() as db:
        new = Model(code="QOLIP-CHECK", name="Qolip check", status="approved",
                    details_json={"general": {"qolip_no": "QC-200" if number else " "}})
        db.add(new)
        db.flush()
        db.add(ModelImage(model_id=new.id, image_type="pattern" if file else "model", file_url="/fixtures/fake.dxf"))
        mid = new.id
        before = (db.query(BrandedPlanningOrder).count(), db.query(ProductionOrder).count())
    request = payload(mid)
    for path, data in (
        ("/api/planning/branded-orders", {"production": request}),
        ("/api/planning/create-branded-production", request),
        ("/api/production-orders", request),
    ):
        result = client.post(path, headers=auth_headers, json=data)
        assert result.status_code == 409, result.text
        assert missing in result.json()["detail"]
    with TestSessionLocal() as db:
        assert (db.query(BrandedPlanningOrder).count(), db.query(ProductionOrder).count()) == before


def test_valid_bso_persists_with_first_production_and_no_empty_order(client, auth_headers):
    blank = client.post("/api/planning/branded-orders", headers=auth_headers, json={})
    assert blank.status_code == 409, blank.text
    complete = client.post("/api/planning/branded-orders", headers=auth_headers,
                           json={"ordered_for_type": "besttex", "production": payload()})
    assert complete.status_code == 201, complete.text
    row = complete.json()
    assert row["ordered_for_name"] == "Besttex"
    assert row["production_count"] == 1
    assert row["total_quantity"] == 10


def test_bso_checks_every_model_used_on_the_order(client, auth_headers):
    with TestSessionLocal.begin() as db:
        other = Model(code="QOLIP-OTHER", name="Second model", status="approved")
        db.add(other)
        db.flush()
        request = payload()
        request["items"][0]["model_id"] = other.id
    result = client.post("/api/planning/create-branded-production", headers=auth_headers, json=request)
    assert result.status_code == 409, result.text


@pytest.mark.parametrize("source_variant", ["", "V-6679"])
def test_bso_uses_one_family_pattern_without_copying_it(client, auth_headers, source_variant):
    existing = client.post("/api/planning/branded-orders", headers=auth_headers, json={"production": payload()})
    assert existing.status_code == 201, existing.text
    order_id = existing.json()["id"]
    with TestSessionLocal.begin() as db:
        source = Model(
            code=f"PM7012-{source_variant}" if source_variant else "PM7012",
            name="Pyjamas", status="approved",
            details_json={"general": {"model_no": "PM7012", "variant_no": source_variant, "qolip_no": "PM7012"}},
        )
        selected = Model(
            code="PM7012-V-6413", name="Pyjamas", status="approved",
            details_json={"general": {"model_no": "PM7012", "variant_no": "V-6413", "qolip_no": "PM7012"}},
        )
        db.add_all([source, selected])
        db.flush()
        db.add(ModelImage(model_id=source.id, image_type="pattern", file_url="/fixtures/pm7012.gemx"))
        source_id, selected_id = source.id, selected.id

    request = payload(selected_id)
    request["planning_order_id"] = order_id
    created = client.post("/api/planning/create-branded-production", headers=auth_headers, json=request)
    assert created.status_code == 201, created.text

    # Alternate entry points share the rule, including when the variant is an item model.
    item_request = payload()
    item_request["items"][0]["model_id"] = selected_id
    for path, data in (
        ("/api/planning/branded-orders", {"production": item_request}),
        ("/api/production-orders", item_request),
    ):
        result = client.post(path, headers=auth_headers, json=data)
        assert result.status_code == 201, result.text

    with TestSessionLocal() as db:
        production = db.get(ProductionOrder, created.json()["id"])
        assert production.planning_order_id == order_id
        assert production.model_id == production.items[0].model_id == selected_id
        assert db.query(WorkOrder).filter_by(production_order_id=production.id, operation="cutting").count() == 1
        assert db.query(ModelImage.model_id).filter(ModelImage.model_id.in_([selected_id, source_id])).all() == [(source_id,)]


def test_bso_does_not_use_patterns_from_other_families_or_catalog_scopes(client, auth_headers):
    with TestSessionLocal.begin() as db:
        models = [
            Model(code=code, name="Pyjamas", status="approved", catalog_scope=scope, factory_code=factory,
                  details_json={"general": {"model_no": family, "qolip_no": "PM7012"}, "legacy_import": legacy})
            for code, family, scope, factory, legacy in (
                ("PM7012-V-6413", "PM7012", "standard", None, False),
                ("PM70120-V-6413", "PM70120", "standard", None, False),
                ("PM7012-U-6413", "PM7012", "usluga", "ECO", False),
                ("PM7012-V-6000", "PM7012", "standard", "ECO", False),
                ("PM7012-V-5000", "PM7012", "standard", None, True),
            )
        ]
        db.add_all(models)
        db.flush()
        selected, *other_models = models
        db.add_all([ModelImage(model_id=row.id, image_type="pattern", file_url="/fixtures/other.dxf")
                    for row in other_models])
        selected_id = selected.id

    result = client.post("/api/planning/create-branded-production", headers=auth_headers, json=payload(selected_id))
    assert result.status_code == 409, result.text
    assert "Attach the Qolip file" in result.json()["detail"]
