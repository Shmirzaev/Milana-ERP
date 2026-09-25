import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.models import (
    AuditLog,
    MaterialReservation,
    Model,
    ProductionBatch,
    ProductionOrder,
    ProductionOrderItem,
    ProductionOrderMaterial,
)
from app.schemas.production import ProductionOrderIn
from app.services.production import expand_production_size_range_items


_MAX_ROWS = 1000
_ROWS = {
    "materials": {"stock_batch_id": 1, "estimated_quantity": 1, "unit": "kg"},
    "items": {"model_id": 1, "color": "navy", "size": "M", "planned_quantity": 1},
    "batches": {"planned_quantity": 1},
}


def _payload(field: str, count: int) -> dict:
    return {
        "production_type": "branded_stock",
        "model_id": 1,
        field: [_ROWS[field].copy() for _ in range(count)],
    }


def _write_counts() -> tuple[int, ...]:
    with SessionLocal() as db:
        return tuple(
            db.query(model).count()
            for model in (
                ProductionOrder,
                ProductionOrderItem,
                ProductionOrderMaterial,
                ProductionBatch,
                MaterialReservation,
                AuditLog,
            )
        )


@pytest.mark.parametrize("field", _ROWS)
def test_production_order_lists_accept_1000_and_reject_1001(field):
    assert len(getattr(ProductionOrderIn.model_validate(_payload(field, _MAX_ROWS)), field)) == _MAX_ROWS
    with pytest.raises(ValidationError) as exc:
        ProductionOrderIn.model_validate(_payload(field, _MAX_ROWS + 1))
    assert any(error["loc"] == (field,) and error["type"] == "too_long" for error in exc.value.errors())


@pytest.mark.parametrize("field", _ROWS)
def test_oversized_production_order_list_rejects_before_writes_and_preserves_auth(client, auth_headers, field):
    body = _payload(field, _MAX_ROWS + 1)
    before = _write_counts()

    unauthenticated = client.post("/api/production-orders", json=body)
    assert unauthenticated.status_code == 401, unauthenticated.text
    assert _write_counts() == before

    authenticated = client.post("/api/production-orders", headers=auth_headers, json=body)
    assert authenticated.status_code == 422, authenticated.text
    assert _write_counts() == before


def _range_items(count: int) -> list[dict]:
    return [
        {"model_id": 1, "color": "navy", "size": "0-98", "planned_quantity": 50}
        for _ in range(count)
    ]


def test_production_size_ranges_cannot_expand_past_1000_persisted_items():
    assert len(expand_production_size_range_items(_range_items(20))) == _MAX_ROWS
    with pytest.raises(HTTPException, match="after size expansion") as exc:
        expand_production_size_range_items(_range_items(21))
    assert exc.value.status_code == 422


def test_production_size_range_expansion_rejects_before_writes_with_auth_and_reference_precedence(
    client, auth_headers,
):
    with SessionLocal() as db:
        model_id = db.query(Model.id).filter(
            Model.status == "approved", Model.catalog_scope == "standard",
        ).order_by(Model.id).scalar()
    assert model_id is not None
    body = {
        "production_type": "branded_stock",
        "model_id": model_id,
        "items": [{**row, "model_id": model_id} for row in _range_items(21)],
    }
    assert len(ProductionOrderIn.model_validate(body).items) == 21
    before = _write_counts()

    assert client.post("/api/production-orders", json=body).status_code == 401
    missing_reference = client.post(
        "/api/production-orders",
        headers=auth_headers,
        json={**body, "model_id": 2_147_483_647},
    )
    assert missing_reference.status_code == 404, missing_reference.text
    rejected = client.post("/api/production-orders", headers=auth_headers, json=body)
    assert rejected.status_code == 422, rejected.text
    assert "after size expansion" in rejected.text
    assert _write_counts() == before
