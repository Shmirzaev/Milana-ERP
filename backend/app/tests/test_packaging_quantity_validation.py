import pytest

from app.models import Department, PackagingRecord, WorkOrder
from app.schemas.production import PackagingRecordIn
from app.tests.conftest import TestSessionLocal
from app.tests.test_sewing_corrections import setup_record


@pytest.mark.parametrize("quantities", [
    {"input_qty": -1, "packed_qty": 0},
    {"input_qty": 10, "packed_qty": -1},
    {"input_qty": 10, "packed_qty": 5, "damaged_qty": -1},
    {"input_qty": 10, "packed_qty": 11},
    {"input_qty": 10, "packed_qty": 9, "damaged_qty": 2},
    {"input_qty": 2**31, "packed_qty": 0},
])
def test_packaging_rejects_invalid_quantities_without_writes(client, auth_headers, quantities):
    _, source_id, _ = setup_record()
    with TestSessionLocal.begin() as db:
        source = db.get(WorkOrder, source_id)
        target = WorkOrder(production_order_id=source.production_order_id,
                           department_id=db.query(Department.id).filter_by(code="PKG").scalar(),
                           operation="packaging", status="in_progress",
                           planned_input_qty=100, planned_output_qty=100)
        db.add(target)
        db.flush()
        target_id = target.id
    response = client.post("/api/packaging/records", headers=auth_headers,
                           json={"work_order_id": target_id, **quantities})
    assert response.status_code == 422, response.text
    with TestSessionLocal() as db:
        assert db.query(PackagingRecord).filter_by(work_order_id=target_id).count() == 0
        target = db.get(WorkOrder, target_id)
        assert (target.actual_input_qty, target.actual_output_qty, target.passed_qty, target.failed_qty) == (0, 0, 0, 0)


@pytest.mark.parametrize("quantities", [(10, 9, 1), (10, 7, 0), (0, 0, 0)])
def test_packaging_accepts_balanced_partial_and_empty_records(quantities):
    received, packed, damaged = quantities
    value = PackagingRecordIn(work_order_id=1, input_qty=received, packed_qty=packed, damaged_qty=damaged)
    assert (value.input_qty, value.packed_qty, value.damaged_qty) == quantities
