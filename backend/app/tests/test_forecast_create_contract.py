"""Creation contract and explicit preservation of unknown historical readers."""
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.libs.dto.planning.forecast_recommendation_input import ForecastRecommendationIn
from app.libs.enums.planning import ForecastRecommendationStatus, ForecastRecommendationType
from app.main import app
from app.models.planning import forecasting_recommendations_service as service
from app.schemas import AuditLog, ForecastRecommendation, Model


@pytest.mark.parametrize("value", ["branded_stock_production", "item_reorder"])
def test_input_uses_actual_enum_and_preserves_open_metadata(value):
    payload = ForecastRecommendationIn(
        recommendation_type=value, suggested_quantity="1.23456", confidence="manual-other",
        source_json={"unknown": [1, {"old": True}], "type": "custom"},
    )
    assert isinstance(payload.recommendation_type, ForecastRecommendationType)
    assert payload.model_dump(mode="json")["recommendation_type"] == value
    assert payload.suggested_quantity == Decimal("1.23456")
    assert payload.confidence == "manual-other"


@pytest.mark.parametrize("value", [" ITEM_REORDER ", "ITEM_REORDER", "unknown", "", None])
def test_type_has_no_new_normalization_or_expanded_members(value):
    with pytest.raises(ValidationError):
        ForecastRecommendationIn(recommendation_type=value, suggested_quantity=1)


def test_only_create_response_is_canonical_in_openapi():
    schema = app.openapi()
    routes = schema["paths"]["/api/forecasting/recommendations"]
    created = routes["post"]["responses"]["201"]["content"]["application/json"]["schema"]
    listed = routes["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert created["$ref"].endswith("/ForecastRecommendationCreatedOut")
    assert listed["items"]["$ref"].endswith("/ForecastRecommendationOut")
    definitions = schema["components"]["schemas"]
    assert definitions["ForecastRecommendationType"]["enum"] == ["branded_stock_production", "item_reorder"]
    assert definitions["ForecastRecommendationStatus"]["enum"] == ["open", "accepted", "dismissed", "converted"]
    assert definitions["ForecastRecommendationOut"]["properties"]["status"]["type"] == "string"


def test_unknown_historical_values_remain_readable_and_reviewable(client, auth_headers):
    with SessionLocal() as db:
        model = Model(code="LEGACY-FC-"+uuid4().hex[:8], name="Legacy", factory_code="MIL")
        db.add(model); db.flush()
        row = ForecastRecommendation(
            recommendation_type="old_custom_type", status=" OLD_STATUS ", model_id=model.id,
            suggested_quantity=2, confidence="custom_conf", source_json=["old", 4],
        )
        db.add(row); db.commit(); row_id = row.id
    listed = client.get("/api/forecasting/recommendations", params={"status": " OLD_STATUS "}, headers=auth_headers)
    assert listed.status_code == 200, listed.text
    entry = next(row for row in listed.json() if row["id"] == row_id)
    assert (entry["recommendation_type"], entry["status"], entry["confidence"], entry["source_json"]) == ("old_custom_type", " OLD_STATUS ", "custom_conf", None)
    reviewed = client.patch(f"/api/forecasting/recommendations/{row_id}", json={"status": "accepted"}, headers=auth_headers)
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["recommendation_type"] == "old_custom_type"
    with SessionLocal() as db:
        saved = db.get(ForecastRecommendation, row_id)
        assert saved.source_json == ["old", 4] and saved.status == "accepted"


def test_http_creation_uses_schema_session_trusted_actor_and_metadata(client, auth_headers, monkeypatch):
    calls = []
    original = service.insert_forecast_recommendation
    def observe(db, command):
        assert isinstance(command.recommendation_type, ForecastRecommendationType)
        assert command.status is ForecastRecommendationStatus.OPEN
        row = original(db, command)
        assert row in db and db.in_transaction()
        calls.append((db, command, row.id))
        return row
    monkeypatch.setattr(service, "insert_forecast_recommendation", observe)
    with SessionLocal() as db:
        model = Model(code="CREATE-FC-"+uuid4().hex[:8], name="Create", factory_code="MIL")
        db.add(model); db.commit(); model_id = model.id
    source = {"custom": [1, {"ok": True}], "model_code": "Preserved display"}
    response = client.post("/api/forecasting/recommendations", headers=auth_headers, json={
        "recommendation_type": "item_reorder", "model_id": model_id,
        "suggested_quantity": "12.34567", "confidence": "manual-other", "source_json": source,
        "created_by": 2147483647, "status": "converted", "reviewed_by": 2147483647,
    })
    assert response.status_code == 201, response.text
    data = response.json()
    assert len(calls) == 1 and data["id"] == calls[0][2]
    assert data["status"] == "open" and data["reviewed_by"] is None
    assert data["created_by"] != 2147483647
    assert data["source_json"] == source and data["confidence"] == "manual-other"
    assert data["suggested_quantity"] == pytest.approx(12.3457)
    with SessionLocal() as db:
        audit = db.query(AuditLog).filter(AuditLog.entity_type == "ForecastRecommendation", AuditLog.entity_id == data["id"]).one()
        assert audit.action == "create_forecast_recommendation"
        assert audit.new_value_json["recommendation_type"] == "item_reorder"
