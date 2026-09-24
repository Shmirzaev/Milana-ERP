from types import SimpleNamespace
from uuid import uuid4

from app.api.routes import production
from app.models import AuditLog, Department, Model, ProductionOrder, SewingRecord, WorkOrder
from app.schemas.production import SewingRecordIn
from app.tests.conftest import TestSessionLocal


_MAX_ROWS = 1000


def _size_rows(count: int) -> list[dict[str, int | str]]:
    return [{"size": "M", "quantity": 1} for _ in range(count)]


def _payload(work_order_id: int, rows: list[dict[str, int | str]]) -> dict:
    return {
        "work_order_id": work_order_id,
        "input_qty": 0,
        "sewn_qty": 0,
        "passed_qty": 0,
        "size_quantities": rows,
    }


def _sewing_work_order() -> int:
    with TestSessionLocal() as db:
        order = ProductionOrder(
            production_no=f"SEW-SIZE-BOUND-{uuid4().hex[:10].upper()}",
            production_type="branded_stock",
            model_id=db.query(Model.id).order_by(Model.id).scalar(),
            status="in_progress",
            planned_quantity=0,
        )
        db.add(order)
        db.flush()
        work_order = WorkOrder(
            production_order_id=order.id,
            department_id=db.query(Department.id).filter_by(code="SEW").scalar(),
            operation="sewing",
            status="in_progress",
        )
        db.add(work_order)
        db.commit()
        return work_order.id


def _write_counts() -> tuple[int, int]:
    with TestSessionLocal() as db:
        return (
            db.query(SewingRecord).count(),
            db.query(AuditLog).filter_by(entity_type="SewingRecord").count(),
        )


def test_sewing_size_quantity_accepts_1000_input_rows_and_preserves_aggregation(monkeypatch):
    monkeypatch.setattr(
        production,
        "_sewing_size_progress_payload",
        lambda _db, _work_order, _batch_id: {
            "remaining_quantity": _MAX_ROWS,
            "items": [],
        },
    )
    payload = SewingRecordIn(
        work_order_id=1,
        input_qty=_MAX_ROWS,
        sewn_qty=_MAX_ROWS,
        passed_qty=_MAX_ROWS,
        size_quantities=_size_rows(_MAX_ROWS),
    )

    canonical = production._validated_sewing_size_quantities(
        None,
        SimpleNamespace(),
        None,
        payload,
    )

    assert canonical == [{"size": "M", "quantity": _MAX_ROWS}]


def test_sewing_size_quantity_rejects_more_than_1000_before_writes(client, auth_headers):
    work_order_id = _sewing_work_order()
    before = _write_counts()

    response = client.post(
        "/api/sewing/records",
        headers=auth_headers,
        json=_payload(work_order_id, _size_rows(_MAX_ROWS + 1)),
    )

    assert response.status_code == 422, response.text
    assert "size_quantities cannot exceed 1000 rows" in response.text
    assert _write_counts() == before


def test_sewing_size_quantity_cap_preserves_auth_and_missing_work_order_precedence(client, auth_headers):
    body = _payload(2_147_483_647, _size_rows(_MAX_ROWS + 1))
    before = _write_counts()

    unauthenticated = client.post("/api/sewing/records", json=body)
    missing_work_order = client.post(
        "/api/sewing/records",
        headers=auth_headers,
        json=body,
    )

    assert unauthenticated.status_code == 401, unauthenticated.text
    assert missing_work_order.status_code == 404, missing_work_order.text
    assert _write_counts() == before
