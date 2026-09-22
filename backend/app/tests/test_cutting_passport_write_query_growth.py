from uuid import uuid4

from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import CuttingPassport, Department, Model, ProductionOrder, WorkOrder


def _linked_order() -> int:
    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        cutting_department_id = db.query(Department.id).filter_by(code="CUT").scalar()
        model_id = db.query(Model.id).order_by(Model.id).scalar()
        order = ProductionOrder(
            production_no=f"PERF14-W-{suffix}",
            production_type="branded_stock",
            model_id=model_id,
            status="new",
            planned_quantity=1,
        )
        db.add(order)
        db.flush()
        db.add(WorkOrder(
            production_order_id=order.id,
            department_id=cutting_department_id,
            operation="cutting",
            status="in_progress",
        ))
        db.commit()
        return order.id


def _capture_selects(callback) -> list[str]:
    with SessionLocal() as db:
        engine = db.get_bind()
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select"):
            statements.append(normalized)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        callback()
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    return statements


def test_linked_passport_create_reuses_work_order_department_reads(client, auth_headers):
    order_id = _linked_order()
    passport_no = f"PERF14-W-{uuid4().hex[:8]}"

    statements = _capture_selects(lambda: _post_passport(
        client,
        auth_headers,
        order_id,
        passport_no,
    ))

    # The two existing work-order reads are required: the first preserves
    # authorization precedence and the second preserves the lock order. Each
    # carries the department code, avoiding a separate reference SELECT.
    work_order_reads = [statement for statement in statements if " from work_orders " in statement]
    department_reads = [statement for statement in statements if " from departments " in statement]
    assert len(work_order_reads) == 2
    assert all(" join departments " in statement for statement in work_order_reads)
    assert department_reads == []

    with SessionLocal() as db:
        saved = db.query(CuttingPassport).filter_by(passport_no=passport_no).one()
        assert saved.production_order_id == order_id


def _post_passport(client, auth_headers, order_id: int, passport_no: str):
    response = client.post(
        "/api/cutting-passports",
        headers=auth_headers,
        json={
            "passport_no": passport_no,
            "date": "2026-09-22T00:00:00Z",
            "production_order_id": order_id,
        },
    )
    assert response.status_code == 201, response.text
