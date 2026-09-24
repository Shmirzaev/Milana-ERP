from __future__ import annotations

from app.db.session import SessionLocal
from app.models import AuditLog, ForecastRecommendation


def _payload(confidence):
    return {
        "recommendation_type": "item_reorder",
        "suggested_quantity": 1,
        "confidence": confidence,
    }


def _counts():
    with SessionLocal() as db:
        return db.query(ForecastRecommendation).count(), db.query(AuditLog).count()


def test_forecast_recommendation_rejects_unsupported_confidence_without_writes_and_preserves_precedence(
    client, auth_headers
):
    before = _counts()
    invalid = client.post(
        "/api/forecasting/recommendations",
        json=_payload("f" * 16),
        headers=auth_headers,
    )
    assert invalid.status_code == 422, invalid.text
    assert invalid.json()["detail"] == "confidence must be low, medium, or high"
    assert _counts() == before

    missing_reference = client.post(
        "/api/forecasting/recommendations",
        json={**_payload("unsupported"), "item_id": 2_147_483_647},
        headers=auth_headers,
    )
    assert missing_reference.status_code == 400, missing_reference.text
    assert missing_reference.json()["detail"] == "item_id references a missing record"

    unauthorized = client.post(
        "/api/forecasting/recommendations",
        json=_payload("unsupported"),
    )
    assert unauthorized.status_code == 401, unauthorized.text
    assert _counts() == before


def test_forecast_recommendation_accepts_supported_confidence_and_reads_legacy_values(
    client, auth_headers
):
    for confidence in ("low", "medium", "high", None):
        response = client.post(
            "/api/forecasting/recommendations",
            json=_payload(confidence),
            headers=auth_headers,
        )
        assert response.status_code == 201, response.text
        assert response.json()["confidence"] == confidence

    with SessionLocal() as db:
        legacy = ForecastRecommendation(
            recommendation_type="item_reorder",
            status="open",
            suggested_quantity=1,
            confidence="f" * 16,
        )
        db.add(legacy)
        db.commit()
        legacy_id = int(legacy.id)

    listed = client.get("/api/forecasting/recommendations", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    legacy_row = next(row for row in listed.json() if row["id"] == legacy_id)
    assert legacy_row["confidence"] == "f" * 16
