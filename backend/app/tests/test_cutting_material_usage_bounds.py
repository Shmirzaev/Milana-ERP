import pytest
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.models import (
    AuditLog,
    Bundle,
    CuttingMaterialUsage,
    CuttingRecord,
    StockMovement,
)
from app.schemas.production import CuttingMaterialUsageIn, CuttingRecordIn


MAX_MATERIAL_USAGE = 9_999_999_999.9999


def _usage(quantity):
    return CuttingMaterialUsageIn.model_validate({
        "stock_batch_id": 1,
        "quantity": quantity,
        "unit": "kg",
    })


def _record_payload(quantity):
    return {
        "work_order_id": 1,
        "input_quantity": 0,
        "cut_pieces": 0,
        "passed_pieces": 0,
        "materials": [{
            "stock_batch_id": 1,
            "quantity": quantity,
            "unit": "kg",
        }],
    }


def _write_counts():
    with SessionLocal() as db:
        return (
            db.query(CuttingRecord).count(),
            db.query(CuttingMaterialUsage).count(),
            db.query(Bundle).count(),
            db.query(StockMovement).count(),
            db.query(AuditLog).count(),
        )


def test_cutting_material_usage_preserves_float_contract_and_storage_boundary():
    ordinary = _usage("12.34567")
    maximum = _usage(str(MAX_MATERIAL_USAGE))
    nested = CuttingRecordIn.model_validate(_record_payload("1.25"))

    assert isinstance(ordinary.quantity, float)
    assert ordinary.quantity == 12.34567
    assert maximum.quantity == MAX_MATERIAL_USAGE
    assert nested.materials[0].quantity == 1.25


@pytest.mark.parametrize(
    "quantity",
    ["NaN", "Infinity", "-Infinity", "0", "-0.0001", "10000000000"],
)
def test_cutting_material_usage_rejects_invalid_or_unrepresentable_values(quantity):
    with pytest.raises(ValidationError):
        _usage(quantity)


@pytest.mark.parametrize("quantity", ["Infinity", "10000000000"])
def test_cutting_material_usage_api_rejects_before_side_effects_and_preserves_auth(
    client,
    auth_headers,
    quantity,
):
    payload = _record_payload(quantity)
    before = _write_counts()

    rejected = client.post("/api/cutting/records", headers=auth_headers, json=payload)
    unauthenticated = client.post("/api/cutting/records", json=payload)

    assert rejected.status_code == 422, rejected.text
    assert unauthenticated.status_code == 401, unauthenticated.text
    assert _write_counts() == before
