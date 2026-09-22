from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import AuditLog, ForecastRecommendation, Role, User
from app.schemas.forecasting import ForecastRecommendationIn


def _payload(quantity) -> dict:
    return {
        "recommendation_type": "item_reorder",
        "item_id": 1,
        "suggested_quantity": quantity,
        "unit": "kg",
        "confidence": "medium",
        "reason": "Forecast quantity boundary regression",
    }


def test_forecast_quantity_accepts_existing_finite_values_and_storage_boundary():
    ordinary = ForecastRecommendationIn.model_validate(_payload("12.34567"))
    maximum = ForecastRecommendationIn.model_validate(_payload("9999999999.9999"))

    assert ordinary.suggested_quantity == Decimal("12.34567")
    assert maximum.suggested_quantity == Decimal("9999999999.9999")


@pytest.mark.parametrize("quantity", ["Infinity", "-Infinity", "NaN", "10000000000"])
def test_forecast_quantity_rejects_nonfinite_and_unrepresentable_values(quantity):
    with pytest.raises(ValidationError):
        ForecastRecommendationIn.model_validate(_payload(quantity))


def test_forecast_quantity_api_rejects_before_writes_and_preserves_auth_precedence(client, auth_headers):
    with SessionLocal() as db:
        denied_role = Role(name=f"No forecast manage {uuid4().hex}", permissions=[])
        db.add(denied_role)
        db.flush()
        denied_user = User(
            name="Denied forecast writer",
            email=f"denied-forecast-{uuid4().hex}@example.com",
            password_hash="unused-forecast-bound-hash",
            role_id=denied_role.id,
            factory_code="MIL",
            extra_permissions=[],
            is_active=True,
        )
        db.add(denied_user)
        db.commit()
        denied_headers = {"Authorization": f"Bearer {create_access_token(denied_user.id)}"}
        before = (db.query(ForecastRecommendation).count(), db.query(AuditLog).count())

    valid = client.post(
        "/api/forecasting/recommendations",
        json=_payload("12.34567"),
        headers=auth_headers,
    )
    assert valid.status_code == 201, valid.text
    assert valid.json()["suggested_quantity"] == pytest.approx(12.3457)

    with SessionLocal() as db:
        after_valid = (db.query(ForecastRecommendation).count(), db.query(AuditLog).count())
    assert after_valid == (before[0] + 1, before[1] + 1)

    for quantity in ("Infinity", "10000000000"):
        response = client.post(
            "/api/forecasting/recommendations",
            json=_payload(quantity),
            headers=auth_headers,
        )
        assert response.status_code == 422, (quantity, response.text)

    assert client.post(
        "/api/forecasting/recommendations",
        json=_payload("Infinity"),
        headers=denied_headers,
    ).status_code == 403
    assert client.post(
        "/api/forecasting/recommendations",
        json=_payload("Infinity"),
    ).status_code == 401

    with SessionLocal() as db:
        after_invalid = (db.query(ForecastRecommendation).count(), db.query(AuditLog).count())
    assert after_invalid == after_valid
