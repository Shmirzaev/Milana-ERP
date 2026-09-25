"""Generic production-order creation only accepts its two standard order types."""

import pytest

from app.db.session import SessionLocal
from app.models import AuditLog, ProductionOrder
from app.schemas.production import ProductionOrderIn


def _write_counts() -> tuple[int, int]:
    with SessionLocal() as db:
        return db.query(ProductionOrder).count(), db.query(AuditLog).count()


@pytest.mark.parametrize("production_type", ["service_order", "other", "", None])
def test_generic_production_order_rejects_unsupported_type_before_writes(
    client, auth_headers, production_type,
):
    payload = {"production_type": production_type, "model_id": 1}
    before = _write_counts()

    unauthenticated = client.post("/api/production-orders", json=payload)
    assert unauthenticated.status_code == 401, unauthenticated.text
    assert _write_counts() == before

    rejected = client.post("/api/production-orders", headers=auth_headers, json=payload)
    assert rejected.status_code == 422, rejected.text
    assert _write_counts() == before


def test_generic_production_type_openapi_vocabulary():
    choices = ProductionOrderIn.model_json_schema()["properties"]["production_type"]["enum"]
    assert choices == ["client_order", "branded_stock"]
