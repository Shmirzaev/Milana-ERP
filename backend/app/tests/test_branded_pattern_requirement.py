import pytest

from app.schemas import BrandedPlanningOrder, Model, ModelImage, ProductionOrder
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
