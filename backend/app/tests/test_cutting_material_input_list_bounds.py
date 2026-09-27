import pytest
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.models import AuditLog, Bundle, CuttingMaterialUsage, CuttingRecord, StockMovement
from app.schemas.production import CuttingRecordIn


_MAX_ROWS = 1000


def _payload(count: int) -> dict:
    return {
        "work_order_id": 2_147_483_647,
        "input_quantity": 0,
        "cut_pieces": 0,
        "passed_pieces": 0,
        "materials": [
            {"stock_batch_id": 1, "quantity": 1, "unit": "kg"}
            for _ in range(count)
        ],
    }


def _write_counts() -> tuple[int, ...]:
    with SessionLocal() as db:
        return tuple(
            db.query(model).count()
            for model in (CuttingRecord, CuttingMaterialUsage, Bundle, StockMovement, AuditLog)
        )


def test_cutting_material_list_accepts_1000_and_rejects_1001():
    assert len(CuttingRecordIn.model_validate(_payload(_MAX_ROWS)).materials) == _MAX_ROWS
    with pytest.raises(ValidationError) as exc:
        CuttingRecordIn.model_validate(_payload(_MAX_ROWS + 1))
    assert any(error["loc"] == ("materials",) and error["type"] == "too_long" for error in exc.value.errors())


def test_oversized_cutting_material_list_rejects_before_writes_and_preserves_auth(client, auth_headers):
    body = _payload(_MAX_ROWS + 1)
    before = _write_counts()

    unauthenticated = client.post("/api/cutting/records", json=body)
    assert unauthenticated.status_code == 401, unauthenticated.text
    assert _write_counts() == before

    authenticated = client.post("/api/cutting/records", headers=auth_headers, json=body)
    assert authenticated.status_code == 422, authenticated.text
    assert _write_counts() == before
