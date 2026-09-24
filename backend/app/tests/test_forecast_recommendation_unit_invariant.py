from uuid import uuid4

from app.models import AuditLog, ForecastRecommendation, Item, Model
from app.tests.conftest import TestSessionLocal


def test_item_recommendation_uses_catalog_unit_without_invalid_writes(client, auth_headers):
    with TestSessionLocal() as db:
        model = Model(
            code=f"FORECAST-UNIT-MODEL-{uuid4().hex[:8]}",
            name="Forecast unit guard model",
            factory_code="MIL",
            status="approved",
        )
        db.add(model)
        db.flush()
        item = Item(
            sku=f"FORECAST-UNIT-{uuid4().hex[:12]}",
            name="Forecast unit guard fabric",
            category="fabric",
            unit="kg",
        )
        db.add(item)
        db.commit()
        model_id = int(model.id)
        item_id = int(item.id)
        before = db.query(ForecastRecommendation).count(), db.query(AuditLog).count()

    payload = {
        "recommendation_type": "item_reorder",
        "model_id": model_id,
        "item_id": item_id,
        "suggested_quantity": 3,
    }
    mismatched = client.post(
        "/api/forecasting/recommendations",
        json={**payload, "unit": "pcs"},
        headers=auth_headers,
    )
    assert mismatched.status_code == 409, mismatched.text
    assert mismatched.json()["detail"] == "Recommendation unit must match the item unit"
    missing = client.post(
        "/api/forecasting/recommendations",
        json={**payload, "item_id": 2_147_483_647, "unit": "pcs"},
        headers=auth_headers,
    )
    assert missing.status_code == 400, missing.text
    assert missing.json()["detail"] == "item_id references a missing record"
    with TestSessionLocal() as db:
        assert (db.query(ForecastRecommendation).count(), db.query(AuditLog).count()) == before

    omitted = client.post("/api/forecasting/recommendations", json=payload, headers=auth_headers)
    assert omitted.status_code == 201, omitted.text
    assert omitted.json()["unit"] == "kg"
    matching = client.post(
        "/api/forecasting/recommendations",
        json={**payload, "unit": "kg"},
        headers=auth_headers,
    )
    assert matching.status_code == 201, matching.text
    assert matching.json()["unit"] == "kg"
    with TestSessionLocal() as db:
        assert db.get(ForecastRecommendation, omitted.json()["id"]).unit == "kg"
        assert db.get(ForecastRecommendation, matching.json()["id"]).unit == "kg"
