from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.models import AuditLog, Model, Notification, PriceCalculationRequest


def _model_with_margin(value) -> int:
    marker = uuid4().hex[:10].upper()
    with SessionLocal() as db:
        model = Model(
            code=f"MARGIN-{marker}",
            name=f"Margin model {marker}",
            status="draft",
            details_json={"general": {"model_no": f"MARGIN-{marker}"}, "costing": {"target_margin_pct": value}},
        )
        db.add(model)
        db.commit()
        return int(model.id)


def _state(model_id: int) -> tuple:
    with SessionLocal() as db:
        model = db.get(Model, model_id)
        assert model is not None
        return (
            deepcopy(model.details_json),
            db.query(PriceCalculationRequest).count(),
            db.query(AuditLog).count(),
            db.query(Notification).count(),
        )


@pytest.mark.parametrize("value", [12.345, 1000000, "Infinity"])
def test_unstoreable_model_margin_does_not_create_price_request_or_side_effects(
    client, auth_headers, value,
):
    model_id = _model_with_margin(value)
    before = _state(model_id)

    response = client.post(
        "/api/price-calculation/requests",
        headers=auth_headers,
        json={"model_id": model_id},
    )

    assert response.status_code == 422, response.text
    assert _state(model_id) == before


@pytest.mark.parametrize("value, expected", [(12.34, Decimal("12.34")), ("12.340", Decimal("12.34")), (999999.99, Decimal("999999.99"))])
def test_storeable_model_margin_creates_price_request(client, auth_headers, value, expected):
    model_id = _model_with_margin(value)

    response = client.post(
        "/api/price-calculation/requests",
        headers=auth_headers,
        json={"model_id": model_id},
    )

    assert response.status_code == 201, response.text
    with SessionLocal() as db:
        request = db.get(PriceCalculationRequest, response.json()["id"])
        assert request is not None
        assert request.profit_percentage == expected
