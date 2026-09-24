import pytest
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.models import AuditLog, ForecastRecommendation, Item, Model
from app.schemas.forecasting import ForecastRecommendationIn


TEXT_LIMITS = {
    "color": 64,
    "size": 32,
    "unit": 32,
}


def _payload(*, item_id: int = 1, model_id: int | None = None, **values) -> dict:
    return {
        "recommendation_type": "item_reorder",
        "model_id": model_id,
        "item_id": item_id,
        "suggested_quantity": "12.3456",
        **values,
    }


@pytest.mark.parametrize(("field", "limit"), TEXT_LIMITS.items())
def test_forecast_recommendation_text_fields_accept_varchar_boundary(field, limit):
    value = "x" * limit
    parsed = ForecastRecommendationIn.model_validate(_payload(**{field: value}))

    assert getattr(parsed, field) == value


@pytest.mark.parametrize(("field", "limit"), TEXT_LIMITS.items())
def test_forecast_recommendation_text_fields_reject_values_beyond_varchar(field, limit):
    with pytest.raises(ValidationError):
        ForecastRecommendationIn.model_validate(_payload(**{field: "x" * (limit + 1)}))


def test_forecast_recommendation_text_overflow_is_rejected_before_writes_and_keeps_auth_precedence(
    client, auth_headers
):
    with SessionLocal() as db:
        model = Model(
            code="FORECAST-TEXT-BOUND-MODEL",
            name="Forecast text-bound model",
            factory_code="MIL",
            status="approved",
        )
        db.add(model)
        db.flush()
        item = Item(
            sku="FORECAST-TEXT-BOUND-UNIT",
            name="Forecast text-bound unit",
            category="fabric",
            unit="u" * TEXT_LIMITS["unit"],
        )
        db.add(item)
        db.commit()
        model_id = int(model.id)
        item_id = int(item.id)
        before = (db.query(ForecastRecommendation).count(), db.query(AuditLog).count())

    valid = client.post(
        "/api/forecasting/recommendations",
        json=_payload(
            item_id=item_id,
            model_id=model_id,
            color="c" * 64,
            size="s" * 32,
            unit="u" * 32,
            confidence="high",
        ),
        headers=auth_headers,
    )
    assert valid.status_code == 201, valid.text

    with SessionLocal() as db:
        after_valid = (db.query(ForecastRecommendation).count(), db.query(AuditLog).count())
    assert after_valid == (before[0] + 1, before[1] + 1)

    for field, limit in TEXT_LIMITS.items():
        response = client.post(
            "/api/forecasting/recommendations",
            json=_payload(item_id=item_id, model_id=model_id, **{field: "x" * (limit + 1)}),
            headers=auth_headers,
        )
        assert response.status_code == 422, (field, response.text)

    assert client.post(
        "/api/forecasting/recommendations",
        json=_payload(item_id=item_id, model_id=model_id, color="x" * 65),
    ).status_code == 401

    with SessionLocal() as db:
        after_invalid = (db.query(ForecastRecommendation).count(), db.query(AuditLog).count())
    assert after_invalid == after_valid
