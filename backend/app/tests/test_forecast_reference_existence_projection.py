from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.api.routes.forecasting import _validate_recommendation_references
from app.models import Brand, Collection, Item, Model
from app.schemas.forecasting import ForecastRecommendationIn
from app.tests.conftest import TestSessionLocal


def _payload(**values):
    return {
        "recommendation_type": "item_reorder",
        "suggested_quantity": 1,
        **values,
    }


def test_forecast_reference_checks_select_only_ids():
    marker = uuid4().hex
    with TestSessionLocal() as db:
        brand = Brand(name=f"Forecast projection {marker}")
        model = Model(code=f"FORECAST-{marker}", name="Reference projection")
        item = Item(
            sku=f"FORECAST-{marker}",
            name="Reference projection item",
            category="fabric",
            unit="kg",
            composition_json=[{"unused": marker}],
        )
        db.add_all([brand, model, item])
        db.flush()
        collection = Collection(brand_id=brand.id, name=f"Forecast {marker}", year=2026)
        db.add(collection)
        db.commit()

        payload = ForecastRecommendationIn.model_validate(_payload(
            model_id=model.id,
            item_id=item.id,
            brand_id=brand.id,
            collection_id=collection.id,
        ))
        statements = []

        def capture(_conn, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.get_bind(), "before_cursor_execute", capture)
        try:
            _validate_recommendation_references(payload, db)
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", capture)

        missing_payload = ForecastRecommendationIn.model_validate(_payload(
            model_id=2_147_000_001,
            item_id=2_147_000_002,
        ))
        with pytest.raises(HTTPException) as exc_info:
            _validate_recommendation_references(missing_payload, db)

    assert len(statements) == 4
    for table in ("models", "items", "brands", "collections"):
        statement = next(sql for sql in statements if f"from {table}" in sql)
        projection = statement.split(f" from {table}", 1)[0]
        assert projection.split()[1] == f"{table}.id"
        assert "," not in projection
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "model_id references a missing record"
