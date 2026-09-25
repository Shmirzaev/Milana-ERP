import pytest
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.models import AuditLog, Bundle, CuttingMaterialUsage, CuttingRecord, StockMovement
from app.schemas.cutting_material import CuttingMaterialDetails
from app.schemas.production import CuttingRecordIn


_NUMERIC_DETAIL_FIELDS = (
    "layer_material_kg",
    "beika_kg",
    "material_rolls_used",
    "waste_quantity",
)


def _record_payload(field: str, value: str) -> dict:
    return {
        "work_order_id": 2_147_483_647,
        "input_quantity": 0,
        "cut_pieces": 0,
        "passed_pieces": 0,
        "materials": [{
            "stock_batch_id": 1,
            "quantity": 1,
            "unit": "kg",
            "details": {field: value},
        }],
    }


def _write_counts() -> tuple[int, ...]:
    with SessionLocal() as db:
        return tuple(
            db.query(model).count()
            for model in (CuttingRecord, CuttingMaterialUsage, Bundle, StockMovement, AuditLog)
        )


@pytest.mark.parametrize("field", _NUMERIC_DETAIL_FIELDS)
def test_cutting_material_details_preserve_float_contract_with_storage_maximum(field):
    ordinary = CuttingMaterialDetails.model_validate({field: "12.34567"})
    maximum = CuttingMaterialDetails.model_validate({field: "9999999999.9999"})
    assert getattr(ordinary, field) == 12.34567
    assert getattr(maximum, field) == 9_999_999_999.9999


@pytest.mark.parametrize("field", _NUMERIC_DETAIL_FIELDS)
def test_cutting_material_details_reject_storage_overflow_before_record_writes(client, auth_headers, field):
    payload = _record_payload(field, "10000000000")
    with pytest.raises(ValidationError):
        CuttingRecordIn.model_validate(payload)
    before = _write_counts()

    unauthenticated = client.post("/api/cutting/records", json=payload)
    assert unauthenticated.status_code == 401, unauthenticated.text
    assert _write_counts() == before

    authenticated = client.post("/api/cutting/records", headers=auth_headers, json=payload)
    assert authenticated.status_code == 422, authenticated.text
    assert _write_counts() == before
