import pytest
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.models import AuditLog, PackagingRecord, WasteRecord
from app.schemas.production import PackagingRecordIn


MAX_SQL_INTEGER = 2_147_483_647


def _write_counts() -> tuple[int, int, int]:
    with SessionLocal() as db:
        return (
            db.query(PackagingRecord).count(),
            db.query(WasteRecord).count(),
            db.query(AuditLog).count(),
        )


def test_packaging_record_quantities_preserve_integer_coercion_and_bounds():
    payload = PackagingRecordIn(
        work_order_id=1,
        input_qty="2147483647",
        packed_qty=0.0,
        damaged_qty=0,
    )

    assert payload.input_qty == MAX_SQL_INTEGER
    assert payload.packed_qty == 0


@pytest.mark.parametrize("field", ["input_qty", "packed_qty", "damaged_qty"])
@pytest.mark.parametrize("value", [True, 1.5, MAX_SQL_INTEGER + 1, -1])
def test_packaging_record_quantities_reject_invalid_sql_integer_values(field, value):
    values = {"work_order_id": 1, "input_qty": 0, "packed_qty": 0, "damaged_qty": 0}
    values[field] = value

    with pytest.raises(ValidationError):
        PackagingRecordIn(**values)


def test_invalid_packaging_record_quantity_has_no_write_side_effects(client, auth_headers):
    before = _write_counts()
    response = client.post(
        "/api/packaging/records",
        headers=auth_headers,
        json={"work_order_id": 1, "input_qty": True, "packed_qty": 0, "damaged_qty": 0},
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before


def test_invalid_packaging_record_quantity_preserves_authentication_precedence(client):
    before = _write_counts()
    response = client.post(
        "/api/packaging/records",
        json={"work_order_id": 1, "input_qty": True, "packed_qty": 0, "damaged_qty": 0},
    )

    assert response.status_code == 401, response.text
    assert _write_counts() == before
