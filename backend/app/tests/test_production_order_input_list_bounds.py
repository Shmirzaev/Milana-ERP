import pytest
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.models import (
    AuditLog,
    MaterialReservation,
    ProductionBatch,
    ProductionOrder,
    ProductionOrderItem,
    ProductionOrderMaterial,
)
from app.schemas.production import ProductionOrderIn


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
